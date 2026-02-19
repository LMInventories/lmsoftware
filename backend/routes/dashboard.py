from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required
from models import db, Inspection, Client, Property, User

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/stats', methods=['GET'])
@jwt_required()
def get_dashboard_stats():
    # Count inspections by status
    created_count = Inspection.query.filter_by(status='created').count()
    assigned_count = Inspection.query.filter_by(status='assigned').count()
    active_count = Inspection.query.filter_by(status='active').count()
    processing_count = Inspection.query.filter_by(status='processing').count()
    review_count = Inspection.query.filter_by(status='review').count()
    complete_count = Inspection.query.filter_by(status='complete').count()
    
    # Count totals
    total_clients = Client.query.count()
    total_properties = Property.query.count()
    total_users = User.query.count()
    total_inspections = Inspection.query.count()
    
    # Get recent inspections (last 5)
    recent_inspections = Inspection.query.order_by(Inspection.created_at.desc()).limit(5).all()
    
    recent_list = []
    for inspection in recent_inspections:
        recent_list.append({
            'id': inspection.id,
            'property_address': inspection.property.address if inspection.property else 'Unknown',
            'client_name': inspection.property.client.name if inspection.property and inspection.property.client else 'Unknown',
            'inspection_type': inspection.inspection_type,
            'status': inspection.status,
            'conduct_date': inspection.conduct_date.isoformat() if inspection.conduct_date else None,
            'created_at': inspection.created_at.isoformat() if inspection.created_at else None
        })
    
    return jsonify({
        'status_counts': {
            'created': created_count,
            'assigned': assigned_count,
            'active': active_count,
            'processing': processing_count,
            'review': review_count,
            'complete': complete_count
        },
        'totals': {
            'clients': total_clients,
            'properties': total_properties,
            'users': total_users,
            'inspections': total_inspections
        },
        'recent_inspections': recent_list
    })
